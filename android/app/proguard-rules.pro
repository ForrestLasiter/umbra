# Keep kotlinx.serialization generated serializers for the core spec models.
-keepclassmembers class com.forrestlasiter.umbra.core.** {
    *** Companion;
}
-keepclasseswithmembers class com.forrestlasiter.umbra.core.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.forrestlasiter.umbra.core.**$$serializer { *; }
