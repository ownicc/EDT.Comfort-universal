package tormozit;

import java.lang.instrument.ClassFileTransformer;
import java.lang.reflect.Constructor;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.ServiceLoader;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

import org.osgi.framework.Bundle;
import org.osgi.framework.Constants;
import org.osgi.framework.hooks.weaving.WeavingHook;
import org.osgi.framework.launch.Framework;
import org.osgi.framework.launch.FrameworkFactory;
import org.osgi.framework.wiring.BundleRevision;
import org.osgi.framework.wiring.FrameworkWiring;

/** Возврат Object вместо Section должен ломать JVM verification на настоящем EDT bytecode. */
public final class DocCommentFramesTest
{
    private static final String COMMENT =
        "com._1c.g5.v8.dt.bsl.documentation.comment.BslDocumentationComment";
    private static final String UTILS =
        "com._1c.g5.v8.dt.bsl.documentation.comment.BslCommentUtils";

    public static void main(String[] args)
    {
        try
        {
            run(args);
        }
        catch (Throwable failure)
        {
            failure.printStackTrace();
            System.exit(1);
        }
        // EDT создаёт фоновые потоки при инициализации модели; каждый сценарий имеет свой JVM.
        System.exit(0);
    }

    private static void run(String[] args) throws Exception
    {
        String mode = args[2];
        var config = new HashMap<String, String>();
        config.put(Constants.FRAMEWORK_STORAGE, Path.of(args[1], "osgi-" + mode).toString());
        config.put(Constants.FRAMEWORK_STORAGE_CLEAN, Constants.FRAMEWORK_STORAGE_CLEAN_ONFIRSTINIT);
        Framework framework = ServiceLoader.load(FrameworkFactory.class).findFirst().orElseThrow()
            .newFramework(config);
        framework.start();
        Object previous = System.getProperties().get(BslDocCommentDescriptionFix.PROP_AFTER_PARSE);
        try
        {
            Bundle target = null;
            List<Path> jars;
            try (var files = Files.list(Path.of(args[0])))
            {
                jars = files.filter(p -> p.toString().endsWith(".jar")
                        || Files.isRegularFile(p.resolve("META-INF/MANIFEST.MF")))
                    .sorted(Comparator.comparing(Path::toString)).toList();
            }
            for (Path jar : jars)
            {
                if (jar.getFileName().toString().startsWith("org.eclipse.osgi_"))
                    continue;
                Bundle bundle = framework.getBundleContext().installBundle("reference:" + jar.toUri());
                if ("com._1c.g5.v8.dt.bsl.comment".equals(bundle.getSymbolicName()))
                    target = bundle;
            }
            if (target == null)
                throw new AssertionError("BSL comment bundle missing");
            FrameworkWiring wiring = framework.adapt(FrameworkWiring.class);
            if (!wiring.resolveBundles(List.of(target)))
            {
                for (Bundle bundle : framework.getBundleContext().getBundles())
                    if (bundle.getState() == Bundle.INSTALLED)
                        for (var requirement : bundle.adapt(BundleRevision.class).getDeclaredRequirements(null))
                            if (wiring.findProviders(requirement).isEmpty()
                                && !"optional".equals(requirement.getDirectives().get("resolution")))
                                System.err.println("Missing: " + bundle.getSymbolicName() + " " + requirement);
            }
            AtomicInteger transformed = new AtomicInteger();
            if (!"stock".equals(mode))
            {
                if ("woven".equals(mode))
                {
                    WeavingHook hook = (WeavingHook) construct("ParseWeavingHook");
                    framework.getBundleContext().registerService(WeavingHook.class, woven -> {
                        if (COMMENT.equals(woven.getClassName()) || UTILS.equals(woven.getClassName()))
                        {
                            System.out.println("weave: " + woven.getClassName());
                            byte[] before = woven.getBytes();
                            hook.weave(woven);
                            if (woven.getBytes() != before)
                                transformed.incrementAndGet();
                        }
                    }, null);
                }
                else
                {
                    ClassFileTransformer transformer = (ClassFileTransformer) construct("ParseClassFileTransformer");
                    framework.getBundleContext().registerService(WeavingHook.class, woven -> {
                        if (!COMMENT.equals(woven.getClassName()) && !UTILS.equals(woven.getClassName()))
                            return;
                        System.out.println("instrumentation: " + woven.getClassName());
                        try
                        {
                            byte[] result = transformer.transform(woven.getBundleWiring().getClassLoader(),
                                woven.getClassName().replace('.', '/'), null, null, woven.getBytes());
                            if (result != null)
                            {
                                woven.setBytes(result);
                                transformed.incrementAndGet();
                            }
                        }
                        catch (Exception failure)
                        {
                            throw new AssertionError(failure);
                        }
                    }, null);
                }
            }
            Class<?> comment = target.loadClass(COMMENT);
            comment.getDeclaredMethods();
            target.loadClass(UTILS).getDeclaredMethods();
            if (!"stock".equals(mode) && transformed.get() != 2)
                throw new AssertionError("Both targets must be transformed: " + transformed);
            var parse = comment.getMethod("parseOldFormat", List.class, List.class);
            AtomicInteger called = new AtomicInteger();
            Object parsed = comment.getConstructor().newInstance();
            for (Object handler : new Object[] { (Consumer<Object>) value -> {
                if (value != parsed)
                    throw new AssertionError("Wrong hook argument");
                called.incrementAndGet();
            }, "not a Consumer" })
            {
                System.getProperties().put(BslDocCommentDescriptionFix.PROP_AFTER_PARSE, handler);
                parse.invoke(parsed, new ArrayList<>(), new ArrayList<>());
            }
            System.getProperties().remove(BslDocCommentDescriptionFix.PROP_AFTER_PARSE);
            parse.invoke(parsed, new ArrayList<>(), new ArrayList<>());
            int expected = "stock".equals(mode) ? 0 : 1;
            if (called.get() != expected)
                throw new AssertionError("Hook calls: " + called + ", expected " + expected);
            System.out.println(mode + ": VERIFIED both classes; parseOldFormat executed; hook calls=" + called);
        }
        finally
        {
            if (previous == null)
                System.getProperties().remove(BslDocCommentDescriptionFix.PROP_AFTER_PARSE);
            else
                System.getProperties().put(BslDocCommentDescriptionFix.PROP_AFTER_PARSE, previous);
            framework.stop();
            framework.waitForStop(10000);
        }
    }

    private static Object construct(String nestedName) throws Exception
    {
        Constructor<?> constructor = Class.forName(BslDocCommentDescriptionFix.class.getName()
            + "$" + nestedName).getDeclaredConstructor();
        constructor.setAccessible(true);
        return constructor.newInstance();
    }
}
